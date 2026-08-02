#!/usr/bin/env python3
"""BM25-through-SEISMIC spike — step 3: rank-fidelity + cost gate.

Three rankers over the identical 208k-doc corpus:

| ranker        | what it is                                                     |
|---------------|----------------------------------------------------------------|
| `exact_vec`   | brute-force dot product over the BM25F vectors (scipy CSR).    |
|               | Exact BM25F **by construction** — the reference SEISMIC is     |
|               | approximating. No pruning, no traversal heuristic.             |
| `seismic`     | the same vectors through `SeismicIndex(LV)` at production      |
|               | params. Difference vs `exact_vec` = SEISMIC's approximation.   |
| `tantivy`     | the production lexical leg (`retriever._bm25f_leg`'s query     |
|               | shape) on a mini index over the same docs.                     |

Separating `exact_vec` from `tantivy` is what makes the result attributable:
`tantivy` vs `exact_vec` isolates formula/tokenizer fidelity (tantivy quantizes
its fieldnorm to u8 and tokenizes at 40 chars where the spike truncates at 28),
while `seismic` vs `exact_vec` isolates the engine's own approximation — the
actual feasibility question. A `seismic`-vs-`tantivy` number alone would
conflate the two.

Reference point for reading the numbers: on SPLADE vectors this same engine
measures **overlap@10 = 0.479 vs exact** (`docs/seismic_150m_testbed/06_FINDINGS.md`,
G2, 2026-06-27), proven to be the query-time approximation floor and not
reclaimable by any index knob. The spike's question is whether BM25 vectors land
better, comparably, or worse than that.

Reads only this spike's `work/` dir plus `data/sfu_eval_queries.json`
(read-only). Touches no serving artifact.

    .venv/bin/python3 spike/bm25_seismic/03_fidelity_gate.py
"""
from __future__ import annotations

import argparse
import json
import logging
import pickle
import resource
import statistics
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp

import bm25_lib as BL

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("bm25seismic.gate")


def rss_gb() -> float:
    with open("/proc/self/status") as fh:
        for line in fh:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1e6
    return 0.0


def peak_rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6


class ExactVectorIndex:
    """Brute-force exact scorer over the SEISMIC jsonl (CSR docs x components)."""

    def __init__(self, jsonl: Path):
        t0 = time.perf_counter()
        ids: list[str] = []
        col_of: dict[str, int] = {}
        indptr = [0]
        indices: list[int] = []
        data: list[float] = []
        with open(jsonl) as fh:
            for line in fh:
                if not line.strip():
                    continue
                rec = json.loads(line)
                ids.append(rec["id"])
                for comp, val in rec["vector"].items():
                    c = col_of.get(comp)
                    if c is None:
                        c = col_of[comp] = len(col_of)
                    indices.append(c)
                    data.append(val)
                indptr.append(len(indices))
        self.ids = np.array(ids)
        self.col_of = col_of
        self.m = sp.csr_matrix(
            (np.asarray(data, dtype=np.float32),
             np.asarray(indices, dtype=np.int32),
             np.asarray(indptr, dtype=np.int64)),
            shape=(len(ids), len(col_of)))
        self.m_csc = self.m.tocsc()
        log.info("exact index: %d docs x %d components, %d nnz in %.1fs",
                 self.m.shape[0], self.m.shape[1], self.m.nnz,
                 time.perf_counter() - t0)

    def search(self, qvec: dict[str, float], k: int) -> list[tuple[str, float]]:
        scores = np.zeros(self.m.shape[0], dtype=np.float32)
        hit = False
        for comp, w in qvec.items():
            c = self.col_of.get(comp)
            if c is None:
                continue
            hit = True
            lo, hi = self.m_csc.indptr[c], self.m_csc.indptr[c + 1]
            # Doc ids within one CSC column are unique, so plain fancy-index
            # accumulation is safe here (np.add.at would be ~10x slower).
            scores[self.m_csc.indices[lo:hi]] += self.m_csc.data[lo:hi] * w
        if not hit:
            return []
        kk = min(k, scores.size)
        top = np.argpartition(-scores, kk - 1)[:kk]
        top = top[np.argsort(-scores[top])]
        return [(str(self.ids[i]), float(scores[i])) for i in top if scores[i] > 0]


def tantivy_search(index, query: str, k: int) -> list[tuple[str, float]]:
    """Query shape copied from `retriever._bm25f_leg`: boolean OR of a
    title query boosted 3.0 and an abstract query, BM25 scored by tantivy.

    The non-alphanumeric scrub is load-bearing and is copied verbatim from
    `_bm25f_leg` (retriever.py). Without it, a hyphen makes tantivy's parser
    build a PHRASE query, and `title`/`abstract` are indexed
    `index_option="freq"` (no positions), so `parse_query` raises
    `ValueError: The field 'title' does not have positions indexed`. Measured
    2026-08-01: skipping this scrub zeroed the tantivy arm on 11 of the 120 SFU
    eval queries (`post-acute`, `real-time`, `land-based`, `off-target`,
    `COVID-19`, `self-determination`, …) and fabricated a ~9.6% quality deficit
    for tantivy that does not exist."""
    import tantivy
    text = "".join(c if c.isalnum() or c.isspace() else " " for c in query)
    if not text.strip():
        return []
    searcher = index.searcher()
    try:
        qt = index.parse_query(text, ["title"])
        qa = index.parse_query(text, ["abstract"])
    except ValueError:
        return []
    q = tantivy.Query.boolean_query([
        (tantivy.Occur.Should, tantivy.Query.boost_query(qt, 3.0)),
        (tantivy.Occur.Should, qa)])
    return [(searcher.doc(addr)["id"][0], float(score))
            for score, addr in searcher.search(q, k).hits]


def overlap_at_k(a: list[str], b: list[str], k: int) -> float:
    sa, sb = set(a[:k]), set(b[:k])
    return len(sa & sb) / k if k else 0.0


def recall_of_in(truth: list[str], cand: list[str], k: int) -> float:
    """Fraction of the exact top-k that appears anywhere in `cand`."""
    t = truth[:k]
    return len(set(t) & set(cand)) / len(t) if t else 0.0


def ndcg_vs_exact(ranked: list[str], truth_scores: dict[str, float],
                  truth_order: list[str], k: int) -> float:
    """NDCG@k using the exact BM25F score as the gain — measures how much true
    BM25F mass a ranker recovers, not just set overlap."""
    def dcg(seq):
        return sum(truth_scores.get(d, 0.0) / np.log2(i + 2)
                   for i, d in enumerate(seq[:k]))
    ideal = dcg(truth_order)
    return float(dcg(ranked) / ideal) if ideal > 0 else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    here = Path(__file__).parent
    ap.add_argument("--work", type=Path, default=here / "work")
    ap.add_argument("--variant", choices=[BL.VARIANT_A, BL.VARIANT_B],
                    default=BL.VARIANT_A)
    ap.add_argument("--queries", type=Path,
                    default=ROOT / "data" / "sfu_eval_queries.json")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--deep-k", type=int, default=100,
                    help="depth at which recall of the exact top-10 is measured")
    ap.add_argument("--query-cut", type=int, default=10,
                    help="production default (SFU_SEISMIC_QUERY_CUT)")
    ap.add_argument("--heap-factor", type=float, default=0.8,
                    help="production default")
    ap.add_argument("--tag", default="",
                    help="index-dir suffix, matching 02_build_indexes.py --tag")
    ap.add_argument("--result-file", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")

    with open(args.work / "stats.pkl", "rb") as fh:
        stats: BL.BM25FStats = pickle.load(fh)
    queries = [q["query"] if isinstance(q, dict) else q
               for q in json.loads(args.queries.read_text())]
    log.info("variant=%s  %d queries  corpus=%d docs",
             args.variant, len(queries), stats.n_docs)

    # ── engines ───────────────────────────────────────────────────────────────
    exact = ExactVectorIndex(args.work / f"vectors_{args.variant}.jsonl")

    import seismic
    import tantivy
    idx_dir = args.work / f"seismic_{args.variant}{args.tag}"
    idx_glob = sorted(idx_dir.glob("*.index.seismic"))
    assert idx_glob, f"no built index in {idx_dir}"
    rss_before = rss_gb()
    t0 = time.perf_counter()
    try:
        sidx = seismic.SeismicIndexLV.load(str(idx_glob[0]))
    except Exception:
        sidx = seismic.SeismicIndex.load(str(idx_glob[0]))
    seismic_load_s = time.perf_counter() - t0
    seismic_rss_delta = rss_gb() - rss_before
    log.info("seismic loaded: len=%d dim=%d nnz=%d in %.1fs (+%.3f GB RSS, stock "
             "owned-RAM load; the mmap layout is format-level and vector-agnostic)",
             sidx.len, sidx.dim, sidx.nnz, seismic_load_s, seismic_rss_delta)
    sdtype = seismic.get_seismic_string()

    tindex = tantivy.Index.open(str(args.work / "tantivy"))
    tindex.reload()

    # ── run ───────────────────────────────────────────────────────────────────
    rows = []
    lat = {"exact_vec": [], "seismic": [], "tantivy": []}
    for n, qt in enumerate(queries, 1):
        qvec = BL.query_vector(qt, stats, args.variant)

        t0 = time.perf_counter()
        ex = exact.search(qvec, args.deep_k)
        lat["exact_vec"].append((time.perf_counter() - t0) * 1000)

        if qvec:
            comps = np.array(list(qvec.keys()), dtype=sdtype)
            vals = np.array(list(qvec.values()), dtype=np.float32)
            t0 = time.perf_counter()
            res = sidx.search(query_id="q", query_components=comps,
                              query_values=vals, k=args.deep_k,
                              query_cut=max(args.query_cut, len(comps)),
                              heap_factor=args.heap_factor)
            lat["seismic"].append((time.perf_counter() - t0) * 1000)
            se = [(doc_id, float(dist)) for (_q, dist, doc_id) in res]
        else:
            se = []

        t0 = time.perf_counter()
        ta = tantivy_search(tindex, qt, args.deep_k)
        lat["tantivy"].append((time.perf_counter() - t0) * 1000)

        ex_ids = [d for d, _ in ex]
        se_ids = [d for d, _ in se]
        ta_ids = [d for d, _ in ta]
        truth_scores = dict(ex)
        k = args.top_k
        rows.append({
            "query": qt,
            "n_query_components": len(qvec),
            "hits": {"exact_vec": len(ex_ids), "seismic": len(se_ids),
                     "tantivy": len(ta_ids)},
            "overlap@%d" % k: {
                "seismic_vs_exact": overlap_at_k(se_ids, ex_ids, k),
                "tantivy_vs_exact": overlap_at_k(ta_ids, ex_ids, k),
                "seismic_vs_tantivy": overlap_at_k(se_ids, ta_ids, k)},
            "recall_exact_top%d_in_%s_top%d" % (k, "seismic", args.deep_k):
                recall_of_in(ex_ids, se_ids, k),
            "ndcg@%d_vs_exact" % k: {
                "seismic": ndcg_vs_exact(se_ids, truth_scores, ex_ids, k),
                "tantivy": ndcg_vs_exact(ta_ids, truth_scores, ex_ids, k)},
            "top1_match": {"seismic": bool(se_ids[:1] == ex_ids[:1]),
                           "tantivy": bool(ta_ids[:1] == ex_ids[:1])},
        })
        if n % 20 == 0:
            log.info("  %d/%d queries", n, len(queries))

    def mean(xs):
        return round(statistics.fmean(xs), 4) if xs else 0.0

    def pct(xs, p):
        return round(np.percentile(xs, p), 2) if xs else 0.0

    k = args.top_k
    summary = {
        "meta": {
            "date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "variant": args.variant,
            "index_tag": args.tag or "(production n_postings=3500)",
            "corpus_docs": stats.n_docs,
            "corpus_source": "social_sciences__recent (spike subset, block-sequential)",
            "n_queries": len(queries),
            "top_k": k, "deep_k": args.deep_k,
            "query_cut": args.query_cut, "heap_factor": args.heap_factor,
            "seismic": {"len": sidx.len, "dim": sidx.dim, "nnz": sidx.nnz,
                        "load_seconds": round(seismic_load_s, 1),
                        "load_rss_delta_gb": round(seismic_rss_delta, 3)},
            "peak_rss_gb": round(peak_rss_gb(), 3),
            "reference": "SPLADE through this engine measures overlap@10 = 0.479 vs "
                         "exact (06_FINDINGS.md G2, 2026-06-27)",
        },
        "scores": {
            f"overlap@{k}_seismic_vs_exact":
                mean([r[f"overlap@{k}"]["seismic_vs_exact"] for r in rows]),
            f"overlap@{k}_tantivy_vs_exact":
                mean([r[f"overlap@{k}"]["tantivy_vs_exact"] for r in rows]),
            f"overlap@{k}_seismic_vs_tantivy":
                mean([r[f"overlap@{k}"]["seismic_vs_tantivy"] for r in rows]),
            f"recall_exact_top{k}_in_seismic_top{args.deep_k}":
                mean([r[f"recall_exact_top{k}_in_seismic_top{args.deep_k}"] for r in rows]),
            f"ndcg@{k}_vs_exact_seismic":
                mean([r[f"ndcg@{k}_vs_exact"]["seismic"] for r in rows]),
            f"ndcg@{k}_vs_exact_tantivy":
                mean([r[f"ndcg@{k}_vs_exact"]["tantivy"] for r in rows]),
            "top1_match_seismic":
                mean([1.0 if r["top1_match"]["seismic"] else 0.0 for r in rows]),
            "top1_match_tantivy":
                mean([1.0 if r["top1_match"]["tantivy"] else 0.0 for r in rows]),
            "empty_result_queries_seismic":
                sum(1 for r in rows if r["hits"]["seismic"] == 0),
        },
        "latency_ms": {eng: {"p50": pct(v, 50), "p95": pct(v, 95),
                             "mean": round(statistics.fmean(v), 2) if v else 0.0}
                       for eng, v in lat.items()},
        "per_query": rows,
    }
    out = args.result_file or (ROOT / "data" / "eval_results" /
                               f"bm25_seismic_spike_fidelity_{args.variant}"
                               f"{args.tag}_{time.strftime('%Y%m%d_%H%M')}.json")
    out.write_text(json.dumps(summary, indent=2))
    log.info("=== BM25-through-SEISMIC fidelity (%s) ===", args.variant)
    for kk, vv in summary["scores"].items():
        log.info("  %-46s %s", kk, vv)
    log.info("  latency ms: %s", summary["latency_ms"])
    log.info("result: %s", out)


if __name__ == "__main__":
    main()
